# MAC-002.1 — Segurança filesystem do UDS

## Identidade da sessão

O Runtime Manager cria um diretório `.jv-*` com modo 0700, abre o diretório e retém `File`/FD mais `dev` e `inode`. A aleatoriedade reduz colisões acidentais; não é autorização contra outro processo do mesmo UID.

O helper começa com o diretório da geração como CWD. O registro limitado no pipe contém o ID, a capability e `dev`/`inode`; não contém o path. Antes do bind, o child abre `.` e compara sua identidade com a recebida. Uma substituição anterior ao spawn que faça o CWD resolver a outro diretório é rejeitada antes de READY. O supervisor também verifica que o nome da sessão ainda aponta ao handle original antes e depois do ACK de readiness.

## Bind e permissões

O child cria `runtime.sock` relativamente ao diretório aberto. `umask(0177)` limita o socket a 0600 no ato do bind, evitando um `chmod(path)` posterior vulnerável a substituição da folha. O diretório fica 0700. A conexão do client usa o path daquela geração; se o nome foi trocado, a prova HMAC ainda falha para socket falso.

## Cleanup ancorado

O parent mantém o FD do diretório original e o child mantém um FD aberto ao seu CWD validado. Ambos removem somente a folha fixa `runtime.sock` com `unlinkat(dirfd, "runtime.sock", 0)`. A operação não resolve novamente o parent pathname. Se o diretório foi renomeado e o nome antigo agora é symlink, o FD ainda aponta ao diretório original; `unlinkat` não atravessa esse symlink.

Assim, o cleanup não usa `canonicalize(path) → remove_file(path)`, `symlink_metadata(path) → remove_file(path)` nem comparação de inode seguida de mutação por pathname. O handle é a âncora da própria mutação. A folha é um nome estático e só a rotina de bind da geração pode criar o socket. Um processo do mesmo UID ainda pode causar DoS ou substituir nomes dentro do diretório privado; isso não faz a operação relativa ao FD alcançar o target externo.

## FFI e dependências

Nenhuma crate foi adicionada. O código usa `File`, `MetadataExt`, permissões Unix e dois símbolos pequenos do sistema (`unlinkat`, `umask`) via FFI; `umask` é chamado somente no processo helper antes do bind. A assinatura é curta, o caminho do unlink é uma constante NUL-terminated e o FD vem do `File` retido. A dependência de ABI é a plataforma Unix/macOS desta tarefa.

## Limite intencional

O socket é removido com segurança, mas o diretório vazio fica preservado no runtime normal. A remoção do próprio diretório exigiria mutar uma entrada no parent por nome mutável sem operação condicional segura disponível nesta implementação. Preservar o diretório vazio é preferível a arriscar apagar uma entrada substituta. Em testes, cleanup auxiliar remove diretórios de teste somente quando o nome ainda corresponde à identidade original.
